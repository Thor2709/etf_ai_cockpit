# ETF coverage audit, 2026-10-09 (ETF1)

Status: implementation complete with offline acquisition tests. The sandbox's
direct HTTP request failed with WinError 10061; live acquisition remains
UNVERIFIED. Both correction-pass decisions are resolved: source acquisition is
wired into refresh, and the existing Comparison page remains unchanged.
The baseline inventory below is retained as historical evidence; the final
correction-pass observations and current handoff supersede its earlier blockers.
The current worker handoff is docs/development/etf-HANDOFF.md.
Worktree: `C:/dev/etf-UI-ETF`, branch `ui/etf`, inspected head
`0ee9a96eb876c7db1bf74bd216cecf8ac850282f`. The worktree was clean before this audit.
Data root: `C:/dev/release/etflive`; no live fetch or data write was performed.

## Evidence boundary

This inventory covers all 16 records whose `instrument_type` is `etf` in the
copy's `configs/universe.yaml`. All 16 are enabled and have persisted scores.
These are observations of the copied artifacts, not a new score run or a
browser click test. Current rendered output and the historical reported VWCE
"no score" are UNVERIFIED; the missing score was not reproduced by this audit.

The table records the original persisted before/after artifacts, which have
not been rewritten. The fresh local recovery check below uses different inputs
and must not be interpreted as a causal score change. Coverage below is the persisted v3
`canonical_coverage`, not the separate legacy `score_coverage` used by the
missing-data display preference. No missing component has been replaced with
zero or an invented observation.

## Every ETF and every E1 field

| ETF | Score before / after (0-10) | Canonical coverage before / after | TER | Tracking difference | Holdings | Country split | Sector split | AUM | Distribution policy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VWCE | 7.9 / 7.9 | 64.539% / 64.539% | Unavailable [TER-MISSING] | Unavailable [TD-MISSING] | 10; 23.7479% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Accumulating [CONFIG] |
| LYP6 | 6.3 / 6.3 | 64.539% / 64.539% | 0.0700% [YF-M] | Unavailable [TD-MISSING] | 10; 19.4857% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Accumulating [CONFIG] |
| SPYK | 7.4 / 7.4 | 64.539% / 64.539% | 0.1800% [YF-M] | Unavailable [TD-MISSING] | 10; 88.9148% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Accumulating [CONFIG] |
| SXRJ_EMU_SMALL | 4.5 / 4.5 | 64.539% / 64.539% | 0.5800% [YF-M] | Unavailable [TD-MISSING] | 10; 11.5542% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Accumulating [CONFIG] |
| EXX1 | 6.2 / 6.2 | 64.539% / 64.539% | 0.5100% [YF-M] | Unavailable [TD-MISSING] | 10; 74.8499% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Distributing [CONFIG] |
| FLXI | 4.2 / 4.2 | 64.539% / 64.539% | 0.1900% [YF-M] | Unavailable [TD-MISSING] | 10; 29.2501% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Distributing [CONFIG] |
| H4ZT | 2.4 / 2.4 | 64.539% / 64.539% | 0.5000% [YF-M] | Unavailable [TD-MISSING] | 10; 97.6745% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Distributing [CONFIG] |
| EUNK | 6.3 / 6.3 | 64.539% / 64.539% | 0.2000% [YF-M] | Unavailable [TD-MISSING] | 10; 21.0185% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |
| SPCX | 5.4 / 5.4 | 64.539% / 64.539% | 0.0800% [YF-M] | Unavailable [TD-MISSING] | 10; 20.8849% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |
| SXRV_NASDAQ100 | 8.3 / 8.3 | 64.539% / 64.539% | 0.3000% [YF-M] | Unavailable [TD-MISSING] | 10; 46.3361% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |
| VFEM | 6.9 / 6.9 | 64.539% / 64.539% | Unavailable [TER-MISSING] | Unavailable [TD-MISSING] | 10; 29.8645% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |
| VUSA | 7.9 / 7.9 | 64.539% / 64.539% | Unavailable [TER-MISSING] | Unavailable [TD-MISSING] | 10; 37.8523% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |
| EUDF | 3.9 / 3.9 | 64.539% / 64.539% | 0.4000% [YF-M] | Unavailable [TD-MISSING] | 10; 82.8294% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |
| XAIX | 8.7 / 8.7 | 64.539% / 64.539% | 0.3500% [YF-M] | Unavailable [TD-MISSING] | 10; 43.8728% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |
| EXUS | 7.3 / 7.3 | 64.539% / 64.539% | 0.1500% [YF-M] | Unavailable [TD-MISSING] | 10; 12.2073% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |
| XDWU | 4.2 / 4.2 | 64.539% / 64.539% | 0.2500% [YF-M] | Unavailable [TD-MISSING] | 10; 42.2988% disclosed [YF-H] | Unavailable [COUNTRY-MISSING] | Unavailable [SECTOR-MISSING] | Unavailable [AUM-DROPPED] | Unavailable [POLICY-MISSING] |

The bracketed codes below specify the source, vintage or exact reason for each
cell. The disclosed weight is the sum of the stored top holdings, not full
holdings coverage and not a normalized estimate. These files do not establish
the total fund holding count.

## Sources, point-in-time limits and gap causes

- **YF-M:** `data/clean/etf_metadata.parquet`, also inspected in
  `data/raw/etf_factsheets/20261009T023631Z_69b02fdc99ae_etf_metadata.parquet`.
  Source `yfinance`, as-of `2026-10-09`; snapshot manifest
  `data/snapshots/etf_metadata/20261009T023631Z_69b02fdc99ae_etf_metadata_metadata.json`
  records ingestion at `2026-10-09T02:36:31.352762+00:00`. The rows have neither
  `source_id` nor `known_at`. Manifest ingestion is observed acquisition
  evidence, not an independently verified issuer publication date or a
  row-level known_at. Earlier decision times must not consume these rows.
- **YF-H:** `data/clean/etf_holdings.parquet`; source column
  `yfinance_top_holdings`, as-of `2026-10-09`. Manifest
  `data/snapshots/etf_holdings/20261009T023631Z_06c04f056315_etf_holdings_metadata.json`
  records ingestion at `2026-10-09T02:36:31.529191+00:00`. These are ten vendor
  top holdings per ETF, with no row-level known_at or typed identity namespace.
  The acquisition date does not prove the issuer's holdings effective date.
- **CONFIG:** `configs/universe.yaml`, explicit boolean `accumulating`.
  This is configuration context, not issuer-confirmed economics evidence;
  dated publication and known_at are unavailable. Do not promote it into
  historical economics or scoring evidence.
- **TER-MISSING:** VWCE, VFEM and VUSA have null TER in the inspected raw and
  clean metadata. The provider only reads the fund-operations expense-ratio
  row and configured TER (`src/etf_cockpit/data/yfinance_provider.py:370`).
  All 16 ETF registry entries for each of factsheet, KID, holdings, methodology
  and prospectus/report are `missing` in `data/clean/etf_disclosures.parquet`;
  `data/clean/priips_kid_records.parquet` has zero rows. No acquired issuer
  fallback is evidenced. An implemented public-page fallback is UNVERIFIED.
- **TD-MISSING:** No `data/**/etf_economics*` artifact exists in this copy.
  No canonical matched ETF/index total-return window was established.
  `src/etf_cockpit/core/paths.py:40` declares the economics and both total-return
  paths. `src/etf_cockpit/application/etf_economics_view.py:28` checks supplied
  records/snapshot attributes; `:53` passes them to the existing calculation.
  Price history alone must not be substituted for an independently sourced
  index total-return series. Tracking difference and its window remain
  unavailable until both distribution-adjusted, comparable series are bound.
- **COUNTRY-MISSING:** Every stored ETF holding has no country column; the
  provider supplies configured fund region (`src/etf_cockpit/data/yfinance_provider.py:410`),
  which cannot establish constituent country. The shared normalizer also maps
  country into region instead of preserving both
  (`src/etf_cockpit/data/reference_data.py:208`). No issuer split is present in
  the inspected reference artifacts. Country classifications must not be
  guessed from names or tickers.
- **SECTOR-MISSING:** Every stored ETF holding has an empty sector, explicitly
  emitted by the provider (`src/etf_cockpit/data/yfinance_provider.py:411`).
  No usable issuer split is evidenced. A residual bucket can represent unknown
  exposure, but cannot make sector classification available.
- **AUM-DROPPED:** The provider emits `total_assets`
  (`src/etf_cockpit/data/yfinance_provider.py:383`), but
  `validate_etf_metadata` builds a narrow frame without AUM
  (`src/etf_cockpit/data/reference_data.py:124`). `commit_reference_import`
  passes that normalized frame to raw storage (`:267`, `:273`); the fallback
  raw writer persists that same frame (`:481`). Neither inspected metadata
  artifact retains total_assets, currency basis or observation provenance.
  Whether Yahoo supplied a numeric value for any ETF is UNVERIFIED: the
  original response has already been discarded. This is a confirmed pipeline
  omission, not proof of any particular missing AUM amount.
- **POLICY-MISSING:** The remaining nine ETF configuration records have null
  `accumulating`, and the inspected metadata schema has no distribution policy.
  No issuer/KID fallback is available in the inspected registry. Names must
  not be used as authoritative policy evidence.
- **UI-E1:** The Fund section currently renders holdings and economics via
  generic `_section_card` calls (`src/etf_cockpit/app/pages/instrument_detail.py:1397`,
  `:1423`), rather than the requested E1 tiles, holdings table and split charts.
  The packet's label-clipping click defect was not visually reproduced here.
- **SECTORS-EMPTY:** The current Sectors loader returns immediately when
  portfolio weights are absent (`src/etf_cockpit/application/ui_views/sectors.py:333`)
  and never reaches its holdings load. It has no universe-weight fallback at
  that branch. Attractiveness/heatmap behavior remains UNVERIFIED by runtime.

## VWCE: fetch, processing, score and display trace

1. **Fetch:** The universe explicitly identifies `VWCE.DE` and
   `IE00BK5BQT80`. `data/clean/prices.parquet` contains 1,271 VWCE observations;
   the latest inspected adjusted close is 172.9199981689453 EUR on
   `2026-10-07`, source yfinance. These are observed values, not a live quote.
   The 2026-10-09 reference capture contains ten top holdings but no TER,
   AUM, country or sector evidence as described above.
2. **Process:** The current score entry point already invokes
   `_generate_missing_price_signals`
   (`src/etf_cockpit/signals/simple_scores.py:769`). That helper computes
   price features, caps recovery to existing signal dates and calls
   `generate_signals(..., publish=False)` (`:701`, `:720`, `:731`). It explicitly
   excludes unbound relative strength (`:724`). This is an existing recovery
   path; no new fix is claimed here. Runtime regeneration was not performed.
3. **Score:** `data/derived/scoreboard.parquet` stores VWCE evidence score
   **7.9/10**, canonical attractiveness **7.6/10**, canonical coverage
   **0.64539**, analysis status `partial`, classification dependency `current`.
   `data/derived/score_components.parquet` records run
   `score_20261009T023815_b62d76f1`. Momentum, trend, risk and liquidity are
   eligible; data quality is eligible but is not an attractiveness-weighted
   component. Missing/excluded legacy composite components are
   `relative_strength`, `etf_exposure`, `baseline`, `timesfm`, `toto`.
   ETF exposure is correctly excluded because its 2026-10-09 vintage is after
   the 2026-10-08 score decision date. Baseline remains advisory, while TimesFM
   and Toto report disabled/missing compatible packages. These are coverage
   gaps, not a reason to remove the available score. The same missing list
   occurs for every ETF in the persisted component artifact.
4. **Display:** `src/etf_cockpit/application/score_views.py:42` builds the
   canonical list. Its optional missing-data adjustment changes an existing
   score toward neutral, without manufacturing a missing score (`:81`).
   `src/etf_cockpit/app/pages/instrument_detail.py:866` prefers that listed
   score for the score card. The older ETF detail page has a separate early
   return when a signal or feature row is missing
   (`src/etf_cockpit/app/pages/etf_detail.py:38`) and displays "No score or
   feature evidence" (`:43`), even though identity remains available. This is
   a concrete display path that can misdescribe a partial pipeline state;
   whether the reported click used this route is UNVERIFIED. No historical
   failing UI snapshot was supplied, so the original no-score root cause
   cannot be asserted from this copy. The current copy already has a score.

The weighted combiner excludes ineligible inputs and divides by available
weight (`src/etf_cockpit/signals/simple_scores.py:637`). Coverage and missing
keys are exposed separately (`:537`, `:548`). Preserve these semantics.

## Original decision, resolved 2026-10-09

The correct end-to-end AUM fix requires the existing shared reference-data
normalizer/publisher in `src/etf_cockpit/data/reference_data.py`, which is outside
ETF1's write set. The packet explicitly requires stopping when a normalizer or
shared persistence change is needed. No alternative parallel persistence path
or UI-time provider fetch was introduced.

Proposed bounded change for the orchestrator: authorize the owner of
`reference_data.py` to retain AUM with explicit units/currency, distribution
policy and distinct country/region dimensions when supplied, and preserve
acquired source/known_at provenance through the existing normalized and raw
publication path. Retain the original provider response before normalization
where it is otherwise discarded. Validate with offline ETF regression fixtures
that the canonical loader can consume the retained evidence point-in-time.
Keep existing validators and atomic publication protections intact. Do not
backfill lost financial values or historical known_at from today's knowledge.
Then resume the allowed ETF loaders, calculations and pages in criterion order.
No edit to `score_views.py`, stock or Sparebank code is proposed.

## Original audit handoff (superseded)

- TASK_ID: ETF1
- Runtime: model=gpt-6.1-sol effort=high
  (Copied packet declaration; effective runtime/model identity is UNVERIFIED.)
- STATUS: blocked; output-contract status PARTIAL.
- FILES_CHANGED: `docs/development/etf-coverage-2026-10.md` only.
- WHAT_CHANGED: preserved the complete copied-data inventory and the confirmed
  shared-normalizer blocker; production code and copied data are unchanged.
- Criterion 1: PARTIAL. Every ETF/E1 field inventoried; VWCE static and persisted
  trace recorded; runtime display and historical no-score reproduction remain
  UNVERIFIED.
- Criterion 2: NOT IMPLEMENTED. All 16 persisted ETF scores already exist;
  runtime regression and stronger all-instrument guarantee remain untested.
- Criterion 3: BLOCKED on shared normalizer authority; fallback and tracking
  golden tests not written or run.
- Criterion 4: NOT IMPLEMENTED. Vendor partial holdings are persisted, but
  constituent classifications and provenance are incomplete.
- Criterion 5: NOT IMPLEMENTED. Requested tiles/table/charts/summary remain.
- Criterion 6: NOT IMPLEMENTED. Universe fallback, attractiveness and heatmap
  remain.
- Criterion 7: NOT IMPLEMENTED. No new fetcher, fixture or network attempt.
- TESTS+RESULTS: 0 pytest tests run, 0 passing, 0 failing. The six required
  tests were not written or run because the mandatory stop was reached before
  behavior changes. The packet validation command was not run. Known failures
  were neither encountered nor suppressed. Final git checks recorded below.
- ASSUMPTIONS/RISKS: tables describe the existing persisted copy, not validated
  new calculation results. Source precedence cannot recover discarded fields.
- NEEDS_OPUS_DECISION: authorize the bounded reference_data.py repair above.
- NEXT_STEP: orchestrator resolves shared-file ownership, then resumes ETF1.

Requested `C:/dev/queues/UI/etf/HANDOFF.md` was not written: that location is
outside the session's writable workspace root and approval policy is `never`.
The complete handoff payload is retained here in an allowed file for the
orchestrator to copy. No permission escalation was attempted.

## Live-fetch command for the orchestrator

Existing yfinance refresh entry point (not run in this session):

```powershell
$env:ETF_COCKPIT_ROOT = 'C:/dev/release/etflive'
python -c "from etf_cockpit.core.config import load_config; from etf_cockpit.application.data_service import DataService; print(DataService(load_config()).refresh_yfinance_data(include_reference_data=True))"
```

This calls the inspected constructor
(`src/etf_cockpit/application/data_service.py:86`) and refresh API (`:181`),
which fetches prices and then reference metadata/holdings (`:222`). It is the
existing vendor fetch, not an implemented issuer/public-page fallback command.
Running it before the normalizer repair will still discard AUM. Its live
success is UNVERIFIED. No URL or identifier has been invented.

## Original audit workspace checks (superseded)

- `git diff --check`: exit 0, no whitespace errors.
- `git diff --stat`: exit 0, empty because the only change is an untracked file.
- `git status --porcelain`: only `?? docs/development/etf-coverage-2026-10.md`.
- `git diff --no-index --check -- NUL docs/development/etf-coverage-2026-10.md`:
  exit 1 (new-file comparison); no whitespace errors, with the Git warning:
  `warning: in the working copy of 'docs/development/etf-coverage-2026-10.md', LF will be replaced by CRLF the next time Git touches it`.
- Python byte/inventory assertions: passed; no CR bytes and exactly 16 ETF data
  rows. LF is present in the actual file; Git configuration was not changed.
- Allowed write set verified: only this permitted documentation file changed.
  No revert, commit, push, tag, dependency or runtime configuration change.


## Resumed implementation and observed results

The approved AUM normaliser repair preserves supplied AUM and its explicit
currency basis for future reference imports. It cannot restore values discarded
by the prior capture. ETF E1 now has a dated per-field source fallback, a
holdings table, country/sector split charts and a deterministic summary.
The old feature-empty detail route reads the shared score list instead of
claiming that absent features imply an absent score.

The local price-recovery check deliberately withheld signals and forecasts,
filtered the copied prices to the 16 configured ETFs, and used the existing
price-feature/signal recovery path without publication. Every configured ETF
had a numeric result. All 16 had canonical coverage **43.2624%**, legacy
component coverage **68.8172%**, and missing components
`relative_strength, etf_exposure, baseline, timesfm, toto`.
This narrower recovery context differs from the stored run (64.539% canonical
coverage); it demonstrates recovery, not an improvement/regression in scores.
The canonical candidate list also contains pending rows, which are excluded
from this configured-ETF observation.

| ETF | Stored before / stored after | Fresh recovery score | Fresh canonical coverage |
| --- | --- | --- | --- |
| VWCE | 7.9 / 7.9 | 7.7 | 43.2624% |
| LYP6 | 6.3 / 6.3 | 6.1 | 43.2624% |
| SPYK | 7.4 / 7.4 | 6.7 | 43.2624% |
| SXRJ_EMU_SMALL | 4.5 / 4.5 | 4.3 | 43.2624% |
| EXX1 | 6.2 / 6.2 | 5.6 | 43.2624% |
| FLXI | 4.2 / 4.2 | 4.0 | 43.2624% |
| H4ZT | 2.4 / 2.4 | 2.0 | 43.2624% |
| EUNK | 6.3 / 6.3 | 6.1 | 43.2624% |
| SPCX | 5.4 / 5.4 | 5.3 | 43.2624% |
| SXRV_NASDAQ100 | 8.3 / 8.3 | 7.7 | 43.2624% |
| VFEM | 6.9 / 6.9 | 6.6 | 43.2624% |
| VUSA | 7.9 / 7.9 | 7.7 | 43.2624% |
| EUDF | 3.9 / 3.9 | 3.5 | 43.2624% |
| XAIX | 8.7 / 8.7 | 8.1 | 43.2624% |
| EXUS | 7.3 / 7.3 | 7.1 | 43.2624% |
| XDWU | 4.2 / 4.2 | 4.0 | 43.2624% |

The E1 loader was also run against the actual copy, with a decision cutoff of
**2026-10-09T02:36:31.529191+00:00**, the latest matching reference acquisition
time. All 16 show ten disclosed holdings. Both splits reconcile to approximately
100%, all in **Other/unclassified**, because the copy has no constituent
country/sector facts. TER remains unavailable for VWCE, VFEM and VUSA
(`ter_missing_all_sources`); the other 13 retain the original yfinance TER
values in the baseline table. All AUM and dated distribution-policy values
remain unavailable (`aum_missing_all_sources`,
`distribution_policy_missing_all_sources`). The baseline configuration policies
for seven instruments are current configuration context, not dated E1 evidence.
Tracking difference remains unavailable because no canonical index/fund return
pair exists. Earlier decision times exclude the later reference capture.

Sectors & Countries now shows the analysed universe when portfolio weights are
absent, labelled **Universe (no portfolio holdings registered)**, with equal
weights and an instruction to register holdings. It conserves unmapped exposure,
uses ETF look-through plus dated direct-stock classification, and shows a
sector-by-metric attractiveness heatmap with coverage/reasons.

Ten new ETF regressions passed, including the captured VWCE price fixture,
source precedence, actual offline yfinance metadata capture, AUM preservation,
distribution-adjusted tracking golden result, future holdings exclusion, E1
rendering, look-through/direct stocks, empty state, and no-portfolio universe
exposure. The prescribed validation results and exact counts are recorded in
etf-HANDOFF.md. Browser rendering and live issuer/public-source acquisition
remain UNVERIFIED. No live endpoint or discarded value was invented.


Resumed broad validation ran 511 tests at its initial checkpoint: 510 passed,
one failed because the new ETF renderer omitted the existing "ETF holdings and
exposure" heading. The heading was restored; all 13 affected Instrument Detail
and new ETF tests then passed. Those were the prior pass's observations.
The owner subsequently authorised refresh wiring and explicitly instructed
that the existing Comparison page remain unchanged; neither decision is open.

## Final correction pass (base 0c240bc8)

The canonical loader and the copied scoreboard/reference artifacts were read
again in this session. All 16 scores and canonical coverage percentages in
the baseline table are unchanged; no copied artifact was rewritten. Current
E1 display evidence at `2026-10-09T02:36:31.529191+00:00` is below. This is a
local readback, not a live fetch. Configuration policy values in the historical
baseline table do not become dated distribution-policy evidence.

| ETF | TER | Tracking difference | Disclosed holdings | Country split | Sector split | AUM | Distribution policy |
| --- | --- | --- | --- | --- | --- | --- | --- |
| VWCE | Unavailable [TER] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| LYP6 | 0.0700% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| SPYK | 0.1800% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| SXRJ_EMU_SMALL | 0.5800% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| EXX1 | 0.5100% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| FLXI | 0.1900% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| H4ZT | 0.5000% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| EUNK | 0.2000% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| SPCX | 0.0800% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| SXRV_NASDAQ100 | 0.3000% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| VFEM | Unavailable [TER] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| VUSA | Unavailable [TER] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| EUDF | 0.4000% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| XAIX | 0.3500% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| EXUS | 0.1500% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |
| XDWU | 0.2500% [M] | Unavailable [TD] | 10 [H] | 100% Other/unclassified [H] | 100% Other/unclassified [H] | Unavailable [AUM] | Unavailable [POLICY] |

- [M]: yfinance metadata, as-of 2026-10-09; matching manifest acquisition
  `2026-10-09T02:36:31.352762+00:00`. Small vendor floating-point differences
  are displayed to four decimal places in percent.
- [H]: yfinance_top_holdings, as-of 2026-10-09, known-at
  `2026-10-09T02:36:31.529191+00:00`. Ten partial rows per fund, with the
  original disclosed fractions retained in the baseline. All classifications
  are missing; Other/unclassified conserves the entire NAV denominator and
  does not claim that every asset actually belongs to an economic sector.
- [TER]: `ter_missing_all_sources`; no dated fee in the copy for the three
  Vanguard ETFs. The new live readers can now attempt document/public fallback.
- [AUM]: `aum_missing_all_sources`; old acquisition discarded fund size.
  The already committed normaliser repair preserves it on the next refresh.
- [POLICY]: `distribution_policy_missing_all_sources`; no dated source policy.
- [TD]: canonical missing list is `benchmark_currency, benchmark_identity,
  benchmark_total_return, closure_policy, currency, fund_economics,
  fund_total_return, matched_total_return`. Price history alone is insufficient
  to supply a bound same-window fund/index total-return pair.

`DataService.refresh_yfinance_data` now attempts issuer documents, public
profiles, then the existing yfinance readers. GETs have ten-second timeouts,
size/redirect bounds and offline HTTP tests. Each source's effective/known-at
dates and failure reasons survive the existing reference importer; all source
values are retained as alternates. Issuer allocations can fill classifications
missing from partial holdings. Unsupported formats remain unavailable.

The public endpoint was verified at
[the VWCE profile](https://www.justetf.com/en/etf-profile.html?isin=IE00BK5BQT80).
The one fixed issuer binding was verified against
[Vanguard's VWCE factsheet](https://fund-docs.vanguard.com/FTSE_All-World_UCITS_ETF_USD_Accumulating_9679_EU_INT_EN.pdf).
Other document addresses come from registry bindings or discovered factsheet
links. Web-tool retrieval is not the sandbox's acquisition environment and
does not authorize importing those remotely observed values as local data.

Direct sandbox GETs to both justETF and Vanguard failed:
`URLError <urlopen error [WinError 10061] Kan geen verbinding maken omdat de doelcomputer de verbinding actief heeft geweigerd>`.
Consequently no live refresh was run, and live values for each ETF remain
UNVERIFIED. The exact command to run outside this network restriction and the
final validation counts are in etf-HANDOFF.md.

Validation completed: the prescribed run passed 521 tests (0 failed, 311
warnings). After the final bounded reader corrections, all 19 affected ETF
regressions passed again (0 failed, 7 warnings), including all six numbered
required tests. Exact commands and evidence timing are in etf-HANDOFF.md.
