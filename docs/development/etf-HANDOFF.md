# ETF1 worker handoff

- TASK_ID: ETF1
- MODEL/EFFORT: Runtime: model=gpt-6.1-sol effort=high
  (Packet runtime line copied exactly; no child agent was spawned.)
- STATUS: partial
- Output-contract status: PARTIAL
- Branch/worktree: ui/etf, C:/dev/etf-UI-ETF. Changes are uncommitted.

## Per-criterion result

1. Audit: complete copied-artifact inventory for all 16 ETFs is retained in
   etf-coverage-2026-10.md, with the resumed observations appended. VWCE fetch,
   processing, score and display were traced. The historical reported absence
   of a score was not reproducible from this copy; browser click output is
   UNVERIFIED.
2. Score: all 16 configured ETFs returned numeric scores in the local recovery
   check with saved signals/forecasts deliberately withheld. The existing
   recovery engine is reused. The old detail page now uses the shared score
   list, coverage and missing list even when features are absent. Missing
   inputs remain excluded. Zero eligible evidence still has no numeric score
   and names the missing data/processing step; no neutral score was invented.
3. E1: the canonical per-field loader implements issuer/public/vendor priority,
   provenance, dates, alternates and disagreement reporting. The approved AUM
   normaliser repair is implemented and tested. Tracking reuses the existing
   matched canonical total-return calculation, with its window and missing
   steps. PARTIAL: live issuer/public acquisition is not connected to the
   refresh service (see NEEDS_OPUS_DECISION).
4. Holdings: existing persisted snapshots retain their dates. The new projection
   selects a known vintage/source, excludes future data, checks NAV weights,
   derives country/sector splits and exposes Other/unclassified. Issuer split
   fallback is checked when holdings are unavailable. Existing canonical
   persistence was reused; no parallel holdings store was added.
5. ETF page: E1 tiles, disclosed holdings count/top-25 table, both labelled
   charts and a deterministic numerical summary are rendered with the kit and
   chartkit. New E1 output has no raw dictionary/JSON text. Each unavailable
   E1 field has a reason. Control rendering tests passed; browser appearance
   is UNVERIFIED.
6. Sectors: canonical ETF look-through plus dated direct-stock classification;
   sector attractiveness/coverage and sector-by-metric heatmap. Without portfolio
   holdings, equally weighted enabled-universe exposure is labelled
   "Universe (no portfolio holdings registered)" and explains registration.
   Without either holdings or an analysed universe, the explicit empty state
   explains what to add. Unknown exposure is conserved rather than inferred
   from undated current classifications.
7. Offline fetch: source-chain fixtures and the actual yfinance metadata fetcher
   pass offline. All seven required tests exist and ran (ten new tests total).
   Live retrieval was not performed. Live issuer/public refresh integration is
   PARTIAL and outside the write set.

## Score and coverage evidence

The persisted artifacts were not rewritten. Their before/after scores and
canonical coverage remain identical. The fresh recovery run has different
inputs, so changes below are not attributed to this patch. Recovery canonical
coverage is 43.2624% and legacy component coverage is 68.8172% for every ETF.
The missing list is relative_strength, etf_exposure, baseline, timesfm, toto.

| ETF | Persisted before / after | Persisted canonical coverage before / after | Fresh local recovery |
| --- | --- | --- | --- |
| VWCE | 7.9 / 7.9 | 64.539% / 64.539% | 7.7 |
| LYP6 | 6.3 / 6.3 | 64.539% / 64.539% | 6.1 |
| SPYK | 7.4 / 7.4 | 64.539% / 64.539% | 6.7 |
| SXRJ_EMU_SMALL | 4.5 / 4.5 | 64.539% / 64.539% | 4.3 |
| EXX1 | 6.2 / 6.2 | 64.539% / 64.539% | 5.6 |
| FLXI | 4.2 / 4.2 | 64.539% / 64.539% | 4.0 |
| H4ZT | 2.4 / 2.4 | 64.539% / 64.539% | 2.0 |
| EUNK | 6.3 / 6.3 | 64.539% / 64.539% | 6.1 |
| SPCX | 5.4 / 5.4 | 64.539% / 64.539% | 5.3 |
| SXRV_NASDAQ100 | 8.3 / 8.3 | 64.539% / 64.539% | 7.7 |
| VFEM | 6.9 / 6.9 | 64.539% / 64.539% | 6.6 |
| VUSA | 7.9 / 7.9 | 64.539% / 64.539% | 7.7 |
| EUDF | 3.9 / 3.9 | 64.539% / 64.539% | 3.5 |
| XAIX | 8.7 / 8.7 | 64.539% / 64.539% | 8.1 |
| EXUS | 7.3 / 7.3 | 64.539% / 64.539% | 7.1 |
| XDWU | 4.2 / 4.2 | 64.539% / 64.539% | 4.0 |

## TESTS+RESULTS

Commands ran from the worktree, with
`$env:ETF_COCKPIT_ROOT='C:/dev/release/etflive'` set for validation.
Pytest uses its existing isolated runtime fixtures. No assertions were weakened,
removed or skipped.

- `python -m pytest -q --tb=line tests/test_etf_completion.py tests/ui/test_page_sectors.py`
  Final result for that stage: 16 passed, 0 failed.
- `python -m pytest -q --tb=line tests/test_etf_completion.py tests/ui/test_page_sectors.py tests/test_architecture_boundaries.py tests/test_flet_layout_contracts.py tests/test_accessibility_contracts.py tests/test_button_contracts.py`
  Final affected-code evidence: 47 passed, 0 failed. Collection confirmed the
  counts: ETF 9, Sectors 8, architecture 3, layout 2, accessibility 3, buttons 22.
- `python -m pytest -q --tb=line --verbosity=0 tests/test_etf_completion.py`
  Final new-test evidence: 10 passed, 0 failed, 7 warnings, 4.68 seconds.
- `python -m pytest -q --tb=line tests/test_simple_scores.py tests/test_architecture_boundaries.py tests/test_flet_layout_contracts.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/ui tests/test_etf_completion.py`
  Prescribed broad validation: 510 passed, 1 failed (511 tests at startup,
  nine new ETF tests at that checkpoint; final collection is 512 after the
  tenth new test was added). It started before the last bounded source
  corrections; affected-code checks cover those corrections. The sole failure
  was `tests/ui/test_page_instrument_detail.py::test_renders_with_sample_data`:
  `AssertionError: assert 'ETF holdings and exposure' in ...`
  `C:/dev/etf-UI-ETF/tests/ui/test_page_instrument_detail.py:79`
  Restored that existing heading in the new ETF renderer, preserving the
  table and all assertions. None of the listed known failures was encountered.
- `python -m pytest -q --tb=line --verbosity=0 tests/ui/test_page_instrument_detail.py tests/test_etf_completion.py`
  Final correction evidence: 13 passed, 0 failed, 9 warnings, 9.05 seconds.
  No unchanged passing broad suite was rerun.

Initial focused failures, corrected without weakening expectations:

- Five-test run: 4 passed, 1 failed; a second attempt remained 4/1.
  Verbatim failure fingerprint:
  `PermissionError: [WinError 5] Toegang geweigerd: 'C:\dev\etf-UI-ETF\logs\pytest_system_tmp\tmpp8b405fl'`
  A diagnostic `python -m pytest -q --tb=short tests/test_etf_completion.py::test_tracking_difference_golden_reinvests_distribution_and_needs_index`
  ran 1 test, 1 failed and established that importing the older economics test
  module ran a temporary-store parameter fixture during import. The new golden
  test now constructs its own canonical stores under pytest's supplied tmp_path.
- Next five-test run: 4 passed, 1 failed.
  `TypeError: CorporateAction.__init__() got an unexpected keyword argument 'effective_date'`
  Corrected the new fixture to the inspected CorporateAction contract.
- Initial 16-test UI run: 10 passed, 6 failed.
  `IndexError: tuple index out of range`
  `C:/dev/etf-UI-ETF/src/etf_cockpit/app/pages/_p4_common.py:140`
  Corrected the Sectors page to keep the existing three-row grid and place the
  new scope note/heatmap outside that grid. No shared layout code was changed.

## FILES_CHANGED

- src/etf_cockpit/app/pages/etf_detail.py
- src/etf_cockpit/app/pages/instrument_detail.py (new ETF helpers and Fund entries only)
- src/etf_cockpit/app/pages/sectors.py
- src/etf_cockpit/application/etf_economics_view.py
- src/etf_cockpit/application/sector_views.py
- src/etf_cockpit/application/ui_views/sectors.py
- src/etf_cockpit/data/etf_economics.py
- src/etf_cockpit/data/fund_adapters.py
- src/etf_cockpit/data/fund_holdings.py
- src/etf_cockpit/data/reference_data.py (bounded AUM repair only)
- tests/test_etf_completion.py
- tests/fixtures/etf/etflive_vwce_prices.json (280 captured copied-data rows)
- tests/fixtures/etf/economics_sources.json (explicit synthetic offline observations)
- docs/architecture/etf-economics.md
- docs/development/etf-coverage-2026-10.md
- docs/development/etf-HANDOFF.md

## ASSUMPTIONS/RISKS and open gaps

The copied reference acquisition was checked at
2026-10-09T02:36:31.529191+00:00. All 16 ETFs show ten disclosed rows; all
country and sector exposure is Other/unclassified because classifications
were never acquired. TER is still absent for VWCE, VFEM and VUSA. Old AUM
cannot be recovered from discarded responses; a live vendor refresh is needed.
No dated distribution policy or canonical matched index-return pair exists in
this copy. Missing fields have explicit reasons; current configuration is not
promoted into historical source evidence. AUM currency remains unavailable
unless explicitly supplied.

The issuer/public adapter needs real source readers and verified source
bindings; it does not fabricate URLs, identifiers, observations or issuer dates.
The existing live refresh service still directly fetches only yfinance.
No live issuer/public fetch, new production dependency, broker/provider write,
protected desktop data access, port use, commit, push or tag occurred.
The existing side-by-side Comparison surface remains outside this write set;
owner E2 is therefore not complete. The original historical VWCE no-score screen and browser label layout remain
UNVERIFIED. All required tests were retained and run; all numbered criteria
are implemented or explicitly reported above.

## NEEDS_OPUS_DECISION

1. Approve a bounded integration in
`src/etf_cockpit/application/data_service.py:222`, outside this packet's write
set, to bind real issuer/public acquisition readers and call the tested source
adapter before the existing yfinance fallback. Preserve the existing local
publisher, source/known-at provenance, PIT filters and issuer precedence; do
not add another economics/holdings store. The orchestrator must select actual
issuer/public source bindings and supported formats before that integration.
No edit to this file was made.

2. Resolve owner E2, "No side-by-side compare page", against the existing
   Comparison page. `src/etf_cockpit/app/pages/comparison.py` builds A/B
   comparison columns and selectors (inspected `comparison_frame` and the
   existing UI contract tests). That file and the route/navigation wiring are
   outside this write set. Approve the intended route removal/replacement and
   the corresponding contract change; no comparison file/test was edited.

The owner-approved AUM decision is resolved; it is not being requested again.

## Live-fetch command for the orchestrator

This inspected existing command performs a vendor refresh into the approved
copy and now preserves supplied AUM. It does not claim issuer/public acquisition
or historical source backfill. Live success is UNVERIFIED.

```powershell
$env:ETF_COCKPIT_ROOT = 'C:/dev/release/etflive'
$env:PYTHONPATH = 'C:/dev/etf-UI-ETF/src'
python -c "from etf_cockpit.core.config import load_config; from etf_cockpit.application.data_service import DataService; print(DataService(load_config()).refresh_yfinance_data(include_reference_data=True))"
```

## NEXT_STEP

Review the uncommitted in-scope diff, resolve the refresh-service integration
write set/source bindings and E2 Comparison routing, then run the vendor refresh above and verify current
E1 output in the browser. The audit remains the source-data inventory.

Final workspace verification:

- `git diff --stat` and `git status --porcelain` ran; sixteen changed/new files
  were individually checked against the approved write set.
- `git diff --check`: exit 0, no whitespace errors. Git warns about its existing
  LF-to-CRLF checkout setting; no Git configuration was changed.
- Added/modified lines and new files use LF. Two existing mixed/CRLF files keep
  their untouched line endings, avoiding unrelated Stock-section or persistence
  reformatting. Semantic diffs remain limited to the permitted sections.
- No out-of-scope changes remain, and no revert of unrelated work was needed.
  All changes remain uncommitted.
