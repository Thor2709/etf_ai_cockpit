# ETFFIX correction-pass handoff

- TASK_ID: ETFFIX
- MODEL/EFFORT: Runtime: model=gpt-6.1-sol effort=high
- STATUS: done
- Output-contract status: DONE
- Branch/worktree: ui/etf, C:/dev/etf-UI-ETF.
- Exact base/head: e0789e54a98af2a353ee496932b3b4301637751d.
- Earlier commits 0c240bc8 and e0789e54 are retained. Corrections are uncommitted.
- No agents, commits, pushes, provider writes, uploads or tags.

## Correction packet, numbered results

1. Fixed: ETF detail uses the snapshot decision timestamp, including the
   existing benchmark_reference_decision_time when supplied. An explicit as_of
   override follows the same policy. Calendar dates mean the end of that UTC
   day, through its final nanosecond; exact timestamps remain exact. Regressions
   include same-day observations, midnight decisions and next-day exclusion.
2. Fixed: Sectors and ETF detail share one dated direct/reference-holdings
   loader. Each fund lacking usable direct evidence falls back to the fetched
   etf_holdings reference store before exposure projection. The regression
   verifies the empty direct store, reference look-through, direct-stock
   exposure and exclusion of an acquisition after the snapshot decision.
3. Fixed: holdings rank usable authority before vintage. Older usable issuer
   evidence wins over newer conflicting vendor evidence. Eligible alternatives
   are retained in frame attrs; unusable acquisitions carry rejection reasons.
4. Fixed: the selector chooses one eligible acquisition per source and vintage,
   with the latest known_at. Both 70% and 30% repeated-snapshot regressions check
   against inflated totals and exclude a future revision. Mixed calendar/ISO
   timestamps are parsed explicitly, preserving eligible later acquisitions.
5. Fixed: the canonical per-field loader validates split weights before source
   selection, records rejected-source reasons and tries the next source.
   Regressions cover 150%, negative, infinite, nonnumeric and empty preferred
   mappings. Valid partial splits receive Other/unclassified in the loader;
   the view no longer maintains a second split-validation path.
6. Fixed: public country/sector sections are located independently of the top
   holdings section. An offline fixture regression removes that entire section
   and verifies both sourced, dated splits survive.
7. Complete: the prescribed pytest invocation finished against the final
   production/test code: 534 passed, 0 failed, 0 skipped, 311 warnings in
   1125.81s. Exit code 0 was observed; no sandbox limitation prevented it.

## Per-criterion result

1. Audit: retained docs/development/etf-coverage-2026-10.md inventories all
   16 ETFs, E1 values/sources/reasons and VWCE fetch/process/score/display gaps.
   This pass independently read the copied universe and scoreboard: all 16
   ETFs have numeric persisted scores. No score artifact was regenerated.
2. Pipeline: retained implementation; the VWCE fixture regression passed with
   numeric score, coverage and missing components, without zero-filled inputs.
3. E1 data: cutoff and split-validation corrections complete; issuer/public/
   yfinance fallback, provenance and tracking golden tests passed offline.
4. Holdings: authority/vintage/acquisition selection and residual regressions
   passed. Conflicting alternatives remain retained; future evidence excluded.
5. ETF page: retained tiles/table/charts/rendering regression passed. Same-day
   observations and valid fallback splits now reach the panel. Browser
   appearance is UNVERIFIED in this pass.
6. Sectors/countries: fetched reference holdings now feed the existing exposure
   cube at the decision timestamp. Look-through, direct stocks, attractiveness,
   heatmap rendering and explicit empty-state regressions passed.
7. Offline/live fetch: offline source tests passed. No live fetch was attempted
   in this correction pass; network acquisition remains UNVERIFIED. The exact
   orchestrator command is retained below.

## Per-ETF score and coverage, before and after

Read-only scoreboard readback this pass verified these copied persisted values
for all 16 configured ETFs. They were not recalculated or rewritten: before
and after refer to unchanged artifacts, not a causal change in score.

| ETF | Score before / after | Canonical coverage before / after |
| --- | --- | --- |
| VWCE | 7.9 / 7.9 | 64.539% / 64.539% |
| LYP6 | 6.3 / 6.3 | 64.539% / 64.539% |
| SPYK | 7.4 / 7.4 | 64.539% / 64.539% |
| SXRJ_EMU_SMALL | 4.5 / 4.5 | 64.539% / 64.539% |
| EXX1 | 6.2 / 6.2 | 64.539% / 64.539% |
| FLXI | 4.2 / 4.2 | 64.539% / 64.539% |
| H4ZT | 2.4 / 2.4 | 64.539% / 64.539% |
| EUNK | 6.3 / 6.3 | 64.539% / 64.539% |
| SPCX | 5.4 / 5.4 | 64.539% / 64.539% |
| SXRV_NASDAQ100 | 8.3 / 8.3 | 64.539% / 64.539% |
| VFEM | 6.9 / 6.9 | 64.539% / 64.539% |
| VUSA | 7.9 / 7.9 | 64.539% / 64.539% |
| EUDF | 3.9 / 3.9 | 64.539% / 64.539% |
| XAIX | 8.7 / 8.7 | 64.539% / 64.539% |
| EXUS | 7.3 / 7.3 | 64.539% / 64.539% |
| XDWU | 4.2 / 4.2 | 64.539% / 64.539% |

## TESTS+RESULTS

Environment: $env:ETF_COCKPIT_ROOT='C:/dev/release/etflive'.
All six required tests remain in tests/test_etf_completion.py and ran. Each
numbered behavioral correction has its own added regression; parameters add
boundary cases. No assertion was weakened, deleted or skipped. The prior
handoff's pytest claims are superseded by the observed results below.

- Initial command: `python -m pytest -q --tb=line tests/test_etf_completion.py tests/test_etf_live_fetch.py`
  Result: 30 passed, 2 failed (32 cases). Both failures were the newly added
  acquisition regression, parameters weights0 and weights1. Verbatim failure
  line: `E   AssertionError: assert np.False_` at
  `tests/test_etf_completion.py:165`. Actual selected known_at was
  `2026-01-02 00:00:00+00:00`; expected `2026-01-03 12:00:00+00:00`.
  Cause: mixed-format timestamp parsing dropped later acquisitions. The
  selector was corrected; neither assertion was changed.
- `python -m pytest -q --tb=line --verbosity=0 tests/test_etf_completion.py tests/test_etf_live_fetch.py`
  Result: 32 passed, 0 failed, 7 warnings in 5.09s. Breakdown: 22 completion,
  10 live-fetch tests. This ran after all six behavioral fixes; subsequent
  bounded cleanup removed unused imports and cross-fund dataframe attrs.
- `python -m pytest -q --tb=line --verbosity=0 tests/test_simple_scores.py tests/test_architecture_boundaries.py tests/test_flet_layout_contracts.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/ui tests/test_etf_completion.py tests/test_etf_live_fetch.py`
  Result: 534 passed, 0 failed, 0 skipped, 311 warnings in 1125.81s (0:18:45),
  exit code 0. All 22 completion and 10 live-fetch cases passed again after
  the final cleanup. No listed known pre-existing failure was encountered.
  --verbosity=0 overrides the repository's additional -q so pytest prints
  its actual terminal counts. Observed terminal output:
  `=============== 534 passed, 311 warnings in 1125.81s (0:18:45) ================`
- `git diff --check`: passed, no whitespace errors. The final write-set and
  newline verification is recorded below. No ruff or other unnamed check ran.

## FILES_CHANGED / WHAT_CHANGED

- src/etf_cockpit/data/etf_cutoff.py: shared date/timestamp cutoff policy.
- src/etf_cockpit/data/fund_holdings.py: usable-authority/vintage/acquisition
  selection, mixed timestamps, retained alternatives and rejections.
- src/etf_cockpit/data/etf_economics.py: cutoff and canonical split validation.
- src/etf_cockpit/data/etf_e1_fetch.py: independent public composition lookup.
- src/etf_cockpit/application/etf_economics_view.py: snapshot cutoff, shared
  holdings-store fallback and removal of duplicate split validation.
- src/etf_cockpit/application/ui_views/sectors.py: same dated holdings fallback
  and decision cutoff for exposure and constituent evidence.
- tests/test_etf_completion.py: five correction regressions, with parameters.
- tests/test_etf_live_fetch.py: public splits without holdings regression.
- docs/architecture/etf-economics.md: corrected selection/fallback policy.
- docs/development/etf-coverage-2026-10.md: correction policy and observed
  evidence; historical validation claims explicitly superseded.
- docs/development/etf-HANDOFF.md: current handoff and actual validation counts.

All files are within the packet's write set. No shared persistence, score
contract, stock-only, Sparebank, dependency or configuration was changed.

## ASSUMPTIONS/RISKS / open gaps with reasons

Production/live acquisition and browser appearance are UNVERIFIED. The retained
audit lists the copied data's absent Vanguard TER, AUM, dated policy,
constituent classifications and matched fund/index total-return evidence.
These are source gaps, not values this correction pass can invent. Prior
network failures are historical evidence, not rerun results in this pass.
A timestamp is treated literally, including midnight; only an actual calendar
date expands to end of day. No current clock time is substituted for a decision.

## NEEDS_OPUS_DECISION

None. All corrections fit the authorised write set and decision rules.

## Live-fetch command for the orchestrator

Retained from the committed handoff. Run in a network-enabled environment;
this pass did not execute it or claim live acquisition success.

```powershell
$env:ETF_COCKPIT_ROOT = 'C:/dev/release/etflive'
$env:PYTHONPATH = 'C:/dev/etf-UI-ETF/src'
python -c "from etf_cockpit.core.config import load_config; from etf_cockpit.application.data_service import DataService; print(DataService(load_config()).refresh_yfinance_data(include_reference_data=True))"
```

## NEXT_STEP

Orchestrator review and commit. The requested corrections and prescribed
validation are complete. The live-fetch command above remains available for
the orchestrator's network-enabled environment; it was not run here.

## Final workspace verification

`git diff --stat`, `git status --porcelain` and `git diff --check` ran.
All 11 changed/new files match the allowed write set (10 tracked modifications,
one new etf_ data module); no unrelated file needed reverting. Added lines and
the new file use LF; untouched legacy CRLF lines in fund_holdings.py remain.
No whitespace errors were reported. Git only warns about its existing checkout
newline setting. The base/head is unchanged and all corrections are uncommitted.
