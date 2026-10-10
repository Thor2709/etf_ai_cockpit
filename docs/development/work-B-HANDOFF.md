# Work B pipeline handoff
FIXED: Preserved runner hardening in 013b22cd; tests/test_work_b_pipeline_runners.py (6 tests).
FIXED: Forecast CSV rejected by app: empty reference and wrong horizon/model-mode identity.
  scripts/run_forecasts.py; 8e21882e; tests/test_work_b_forecast_publication.py (1 test).
FIXED: Missing/short adjusted history silently omitted baseline rows; now null, unavailable, ineligible.
  src/etf_cockpit/application/forecast_service.py; 7a9ec361; tests/test_work_b_forecast_missing_history.py (2 tests, including future-row exclusion).
FIXED: Signal traces emitted NaN; CLI/explanations exposed missing evidence as numbers and explained raw rather than published scores.
  scripts/run_signals.py, src/etf_cockpit/signals/{signal_pipeline,explanations}.py; 80e96966; tests/test_work_b_signal_reporting.py (3 tests).
VALIDATION: ETF_COCKPIT_ROOT=C:/dev/etf-WORK-B/.owner-root; ETF_COCKPIT_OPEN_BROWSER=0.
VALIDATION: run_forecasts.py, run_signals.py, run_backtest.py and run_yfinance_candidate_forecasts.py exit 0; no tracebacks.
VALIDATION: run_yfinance_analysis.py exit 1, clearly rejects incomplete Yahoo refresh; cached prices retained.
VALIDATION: App snapshot/bound forecast loader read 184 rows (16 baseline OK, 68 baseline unavailable; optional models disabled/unavailable).
VALIDATION: Canonical snapshot scoring wrote scoreboard.parquet; app loader read all 84 rows. Strict JSON signal trace read 16 rows.
VALIDATION: BacktestService cache loader read 7 strategy results; execution_allowed=false throughout.
VALIDATION: Candidate forecasts downloaded 15,323 price rows for 12 instruments; 180 forecast rows, including 60 baseline OK.
VALIDATION: 12 focused tests passed (6 new plus 6 preserved); logs and loader-check scripts retained under .owner-root/.
VALIDATION: Full suite without xdist: baseline stopped at tests/issue0014/test_browser_workflows.py:41 (router.route-error); final passed that check, then stopped at test_packaged_workflows.py:85 because Python lacks build. Full suite is not green.
OUT_OF_SCOPE: Browser route failure is handled at src/etf_cockpit/app/router.py:787; UI owner must diagnose/correct the failing route handler, preserving its error guard.
OUT_OF_SCOPE: tests/issue0014/test_packaged_workflows.py:85 requires the existing build test tool; restore the development test environment before completing packaged-suite validation. No dependency or test was weakened.
NEEDS_NETWORK: None; Yahoo was reachable. Its unavailable symbols are a data/configuration blocker, not a sandbox outage.
REMAINING: Yahoo returned no rows for JEDI/JDEP.AS, RABO/RABO.OL, SADG/SADG.OL; refresh correctly stays closed.
REMAINING: Verify symbol identities against authoritative owner records before changing .owner-root/configs/universe.yaml:647,817,936 and universe_store.json.
REMAINING: Missing histories, benchmark/portfolio evidence and optional weights remain explicitly unavailable; no financial definition changed.
NEEDS_OPUS_DECISION: None; no replacement financial calculation or invented identifier was introduced.
SAFETY: Never read/wrote the owner's install path. All owner-data operations used the private copy; no server, trade, broker/provider write, deployment or push.
GIT: Three root-cause commits on fix/work-B plus this handoff; private data/logs remain untracked and are not committed.
