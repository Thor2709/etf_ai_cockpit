# ETF1 worker handoff

- TASK_ID: ETF1
- MODEL/EFFORT: Runtime: model=gpt-6.1-sol effort=high
- STATUS: done
- Output-contract status: DONE
- Branch/worktree: ui/etf, C:/dev/etf-UI-ETF.
- Exact base: 0c240bc89e79479404a5422d856a5df6f0d554ec.
- The previous implementation remains committed at that base. This correction
  pass is uncommitted. No agents, commits, pushes or comparison-page edits.

## Per-criterion result

1. Audit: DONE. The audit retains all 16 ETFs' original E1/source-gap inventory
   and VWCE fetch/process/score/display diagnosis. This session re-read the
   copied scoreboard and canonical E1 panel for all 16 and appended the current
   field values, source dates and exact reasons. Historical VWCE screen output
   remains UNVERIFIED; the concrete feature-empty display defect was corrected
   in the retained implementation. No copied artifact was rewritten.
2. Pipeline: DONE for the configured ETF universe. All 16 have persisted numeric
   scores; the retained VWCE fixture regression exercises numeric recovery with
   coverage and a missing list. Missing inputs are excluded. Existing canonical
   scoring and score_views contracts were preserved.
3. E1 data: DONE with offline acquisition evidence. Refresh now wires the
   existing source adapter to timed, bounded issuer/public GET readers, then
   the existing yfinance readers. Registered document URLs and an observed
   public factsheet link supply issuer bindings; VWCE also has a verified issuer
   factsheet URL. Unsupported/missing source formats fall through with reasons.
   Source records, alternates, disagreements, dates and known_at survive the
   existing reference importer via its field_name/value columns. Current public
   facts use acquisition-snapshot dates; dated composition and issuer factsheets
   retain effective dates. A bare dollar sign does not establish AUM currency.
   Tracking difference retains the canonical distribution-adjusted same-window
   calculation; absent bound index evidence stays unavailable with exact steps.
4. Holdings: DONE. Dated public top holdings and explicitly identity-bound issuer
   CSV holdings reuse reference persistence. The existing point-in-time vintage
   selection and weight/residual calculation are reused. Countries/sectors are
   never inferred from holding names. Issuer/public allocations can fill
   classifications absent from partial holdings. Canonical holdings remain the
   primary source; source acquisition does not confer scoring authority.
5. ETF page: DONE. The retained implementation renders E1 tiles, top-25 holdings
   table/count, labelled charts and deterministic summary with reasons. The
   correction prevents wholly unclassified partial holdings from masking
   sourced allocations. Offline importer-to-panel evidence verifies issuer
   split provenance after round trip. Browser appearance is UNVERIFIED.
6. Sectors/countries: DONE. Retained canonical look-through/direct-stock exposure,
   dated classification, attractiveness/coverage, heatmap, labelled universe
   fallback and explicit empty states remain covered by the required tests.
   No new comparison page was created; the existing page is unchanged as the
   owner explicitly directed in the correction packet.
7. Offline/live fetch: DONE under the packet's network-unavailable route. HTTP
   stubs cover issuer priority, discovery, public/vendor fallback, missing fee,
   source failures, identity, point-in-time dates, GET/timeouts, persistence and
   DataService wiring. The direct sandbox GET failed with WinError 10061; no
   live refresh ran. The exact external fetch command is below.

## Per-ETF score and coverage, before and after

These are this session's readbacks of unchanged copied artifacts, not a new
published score run. Every row has the same canonical missing list:
relative_strength, etf_exposure, baseline, timesfm, toto. The prior recovery
run used different inputs and is retained only as historical audit evidence.

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

Environment: `$env:ETF_COCKPIT_ROOT='C:/dev/release/etflive'`.
The existing pytest runtime fixtures isolate test writes. All six numbered
required tests exist in tests/test_etf_completion.py and ran. No assertion
was weakened, deleted or skipped. No out-of-scope test was edited.

- `python -m pytest -q --tb=line tests/test_etf_live_fetch.py tests/test_etf_completion.py`
  Initial result: 16 passed, 1 failed. Verbatim failure:
  `ValueError: ETF factsheets contain invalid or missing as_of_date values.`
  `C:/dev/etf-UI-ETF/src/etf_cockpit/data/reference_data.py:275`
  Cause: source observations mixed date strings with ISO timestamps, which
  the existing pandas normaliser parsed as one format. The reader now supplies
  uniform calendar import dates and retains precise timestamps in provenance;
  no normaliser or assertion was changed.
- `python -m pytest -q --tb=line --verbosity=0 tests/test_etf_live_fetch.py tests/test_etf_completion.py`
  After the date correction: 17 passed, 0 failed, 7 warnings.
  After discovery/exception-containment and importer-to-panel coverage were
  added: 19 passed, 0 failed, 7 warnings (9 acquisition + 10 completion tests).
- `python -m pytest -q --tb=line --verbosity=0 tests/test_simple_scores.py tests/test_architecture_boundaries.py tests/test_flet_layout_contracts.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/ui tests/test_etf_completion.py tests/test_etf_live_fetch.py`
  Result: 521 passed, 0 failed, 311 warnings in 1163.50 seconds. No listed
  known failure was encountered. This run started before the bounded AUM
  currency clarification, malformed-context guard and company-name filter
  correction. Final affected evidence is recorded below; unchanged broad
  checks are not repeated.
- `python -m pytest -q --tb=line --verbosity=0 tests/test_etf_live_fetch.py tests/test_etf_completion.py`
  Final affected-code run after all source corrections: 19 passed, 0 failed,
  7 warnings in 5.55 seconds. This includes explicit regressions for ambiguous
  AUM currency, malformed context and real holding names containing Holdings.

## WHAT_CHANGED / FILES_CHANGED (this pass)

- src/etf_cockpit/application/data_service.py: source-chain refresh wiring,
  preserving the existing price and reference publication scopes.
- src/etf_cockpit/data/etf_e1_fetch.py: new bounded GET readers, source discovery,
  dated parsers and existing reference-column provenance encoding/decoding.
- src/etf_cockpit/data/fund_adapters.py: source exceptions fall through with
  redacted detailed reasons; callable cutoff resolves after acquisition.
- src/etf_cockpit/data/etf_economics.py: decode imported context in the canonical
  reference loader and include acquisition failures in unavailable reasons.
- src/etf_cockpit/application/etf_economics_view.py: decode supplied metadata
  and keep sourced allocations when holding classifications are unavailable.
- tests/test_etf_live_fetch.py: offline acquisition/refresh/persistence tests.
- tests/fixtures/etf/public_profile.html: explicitly synthetic offline template.
- docs/architecture/etf-economics.md: source acquisition and provenance routing.
- docs/development/etf-coverage-2026-10.md: current E1 readback and resolved decisions.
- docs/development/etf-HANDOFF.md: this handoff.

All earlier committed implementation files are retained. The shared AUM
normaliser was not further edited. No Comparison page, stock-only, Sparebank,
score-history/settings contract, dependency or protected desktop path changed.

## ASSUMPTIONS/RISKS / open gaps with reasons

Live acquisition is UNVERIFIED because the sandbox cannot connect. Direct GETs to both justETF and Vanguard returned:
`URLError <urlopen error [WinError 10061] Kan geen verbinding maken omdat de doelcomputer de verbinding actief heeft geweigerd>`.
Web-tool source verification is a different environment and was not imported
as financial observations. No live field value or issuer ID was invented.

The unchanged copied data still lacks TER for VWCE/VFEM/VUSA, AUM and dated
policy for all 16, a bound fund/index total-return pair, and constituent
classifications. The current per-ETF values and exact source/reason codes are
in the final audit table. A successful external refresh is needed for new
observations; its success and browser rendering remain UNVERIFIED. Unsupported
issuer templates or an absent optional PDF parser explicitly fall through.
A current public profile date is acquisition context, never a publication date.

## NEEDS_OPUS_DECISION

None. Both prior decisions are resolved by the correction packet. The source
integration file is authorised, and the existing Comparison page is unchanged.
No expanded write set, production dependency or external action is requested.

## Live-fetch command for the orchestrator

Run outside this sandbox's network restriction. This invokes the implemented
issuer/public/yfinance source chain and its existing local publication path:

```powershell
$env:ETF_COCKPIT_ROOT = 'C:/dev/release/etflive'
$env:PYTHONPATH = 'C:/dev/etf-UI-ETF/src'
python -c "from etf_cockpit.core.config import load_config; from etf_cockpit.application.data_service import DataService; print(DataService(load_config()).refresh_yfinance_data(include_reference_data=True))"
```

Then use the canonical ETF E1 panels to record every ETF's actual new values,
sources, dates and remaining reasons. The command makes no provider writes;
only the approved local copy is published. execution_allowed remains false.

## NEXT_STEP

The orchestrator reviews the uncommitted correction and runs the live command
in a network-enabled environment, then records actual per-ETF E1 sources and
values. No commit or push was performed by this worker.

## Final workspace verification

`git diff --stat`, `git status --porcelain` and `git diff --check` ran.
All ten changed/new files match the allowed write set; no unrelated file
needed reverting. Added lines and all three new files use LF. Untouched
legacy CRLF lines in data_service.py were preserved. No whitespace errors
were reported; Git only warns about its existing checkout newline setting.
The branch and base are unchanged, and the correction remains uncommitted.
