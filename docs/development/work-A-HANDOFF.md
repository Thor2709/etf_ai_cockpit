FIXED
- Smoke selected the checkout instead of owner data; scripts/smoke_app.py now preserves ETF_COCKPIT_ROOT and uses checkout acceptance metadata. Tests: tests/test_work_a_smoke_root.py (5 tests).
- Ordinary launcher overwrote a config/data-only install root; scripts/launcher_core.py now separates runtime data from executable code. Test: test_launcher_smoke_preserves_selected_install.
- Older installs lacked seven shipped config registries; core/install_defaults.py and core/runtime.py publish only missing defaults through the existing atomic group mechanism. Existing configs and stored records are preserved.
- Upgrade regression: tests/test_work_a_install_defaults.py::test_owner_upgrade_is_atomic_preserves_records_and_is_idempotent (failure rollback, owner config preservation, schema rerun, byte/mtime equality).
COMMITS
- a9b38708 smoke root; b8d66027 launcher root; startup-default commit includes this handoff.
VALIDATION
- Focused: python -m pytest tests/test_work_a_smoke_root.py tests/test_work_a_install_defaults.py tests/test_launcher_workflow.py tests/test_schema_migrations.py -q --tb=line: 21 passed; six Work A tests total.
- Owner copy: scripts/smoke_app.py --port 8611 passed with ETF_COCKPIT_ROOT=C:/dev/etf-WORK-A/.owner-root and ETF_COCKPIT_OPEN_BROWSER=0.
- Real Flet WebSocket session received Home score cards; loading placeholder removed; no route-error control or server traceback. HTTP root served successfully.
- All started servers stopped; port 8611 verified closed. Evidence: .owner-root/first-page-{frames,server,result}.log.
- Second startup/migration pass: applied_versions=(), 766 config/data files unchanged by hash and mtime; .owner-root/idempotence.log.
- Full serial command: python -m pytest tests -q -x --tb=line -p no:cacheprovider; xdist omitted as instructed.
- Baseline stopped at tests/issue0014/test_browser_workflows.py:41 (router.route-error).
- Final passed that test, then stopped at tests/issue0014/test_packaged_workflows.py:85: No module named build, before app execution. Packaging test/tooling sources are unchanged.
- Logs: .owner-root/{baseline-tests,final-tests,focused-final,build-tooling-repro}.log. Full suite is not green; no application regression observed before -x stopped it.
OUT_OF_SCOPE
- src/etf_cockpit/app/router.py:436: baseline non-Home route-render error; identify and repair the failing route builder if it recurs. Final run passed the all-routes test.
NEEDS_NETWORK
- Startup required none; cached data sufficed. Wheel validation needs missing build tooling installed, potentially requiring a package download; no dependencies installed or changed here.
REMAINING
- Complete wheel/full-suite validation once build tooling is available. No remaining observed owner-copy startup failure.
- No identity guesses or financial-value edits applied; no records dropped or zero-filled; execution_allowed=false retained.
- Owner's original install was never read or written. Only .owner-root was used for owner data; it remains untracked and excluded from commits.
