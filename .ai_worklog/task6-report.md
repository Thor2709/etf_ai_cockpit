# Wave 3 Task 6 report

## Baseline reconciliation

The repository baseline already contains `WorkflowController`, typed
`WorkflowStatus`/`WorkflowStep`/`WorkflowResult`, session trace persistence,
redaction, logging-failure tolerance, dashboard background workers and visible
Activity Log progress. Existing workflow runtime tests cover lifecycle,
terminal-state rejection, redaction, failure fingerprints and logger failure.

## RED evidence

- The new dashboard primary-button accessibility test was run before the
  implementation change and failed for the intended behavioural reason: the
  four keyed controls were `Container` objects rather than focusable buttons.

## GREEN and boundary evidence - 2026-07-12

- RED command: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/test_workflow_runtime.py::test_primary_dashboard_workflows_are_keyboard_operable_buttons` - exit **1**; the four keyed controls were `Container` objects rather than focusable buttons.
- Implemented the smallest compatible change: primary dashboard workflows now use keyboard-operable `ft.OutlinedButton` controls inside the existing layout containers; stable keys/tooltips/callbacks are preserved.
- GREEN runtime bundle: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/test_workflow_runtime.py tests/test_flet_startup.py` - exit **0**, 20 passed.
- Compileall, scoped Ruff and `git diff --check` - exit **0**; no new workflow/session trace failures.
- Existing workflow runtime tests continue to cover start-before-step event ordering, terminal transition rejection, JSON-secret redaction, traceback fingerprints, logger-write tolerance, manual-review/unavailable states and visible Activity Log projection.
- `execution_allowed` remains `false`; no broker, credentials or order routing were added.

## Independent review and evidence correction - 2026-07-12

- Fresh independent reviewer: `/root/task6_workflow_reviewer` (gpt-5.6-sol,
  independent reviewer role).
- Initial review: CODE **PASS**; SPEC **FAIL / not ready** because this report
  did not yet contain package, rendered-source and smoke evidence, and retained
  stale RED wording. No code findings were raised.
- Corrective evidence gathered:
  - `cmd /c scripts\\build_windows.bat` - exit **0**; native executable was
    rebuilt at `build/flet_dist/ETF_AI_Cockpit/ETF_AI_Cockpit.exe`, SHA-256
    `E8874C460953E32D485162A92AF034E44EA0E9985AC7A90DD5BD84E287E2BA42`;
    portable folder created at `build/ETF_AI_Cockpit_Portable_v0.1.0`.
  - `scripts/smoke_app.py --mode source --port 8570 --timeout 60` - exit
    **1** at `_verify_score_groups`: `Sparebanken group did not preserve AURG
    needs_verification ISIN.` The same fixture check fails for native and
    portable-native smoke modes. This is a pre-existing generated-data/worktree
    condition (the worktree has no ignored `data/raw/trade_candidates` fixture),
    not a failure introduced by the button change; it is retained as an
    explicit verification limitation.
  - Direct source launch with Task 6 code and the verified main data root on
    port 8558 rendered the dashboard successfully. The screenshot is
    `evidence/task6-dashboard-source-main-data.png`, SHA-256
    `80964F9BFB05989BEF37CC9E054621451F65FE8C4A7C4464BCE65BF9562F1DF6`.
    It shows the workflow row using the established dark cockpit tokens and
    outlined button treatment; the structural test independently covers all
    four controls, including the rightmost control beyond the screenshot crop.
    A direct rebuilt native executable launch against the same verified main
    data root returned HTTP 200 on port 8561 (`native_direct_ready=True`).
  - A source-root launch against the isolated worktree data correctly exposed
    the existing recovery-required state (`migration blocked by incomplete
    atomic transaction: lock_paths[0] is not a canonical group lock`) in
    `evidence/task6-dashboard-source.png`, SHA-256
    `80FD3CFB9E2CD88CDE15462937117873B288610707E0896295C5018263FC2807`.
- The evidence gap is closed for the code change; the unrelated generated-data
  smoke limitation remains documented and no issue is closed by this task.

## Fresh re-review verification bundle - 2026-07-12

- `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q
  tests/test_workflow_runtime.py tests/test_flet_startup.py
  tests/test_e2e_workflow.py tests/test_button_contracts.py tests/scope_boundary
  tests/test_accessibility_contracts.py` - exit **0**, 29 passed.
- `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m compileall -q
  src tests` - exit **0**.
- Scoped Ruff over the changed dashboard, workflow/session runtime, state and
  test files - exit **0**, `All checks passed!`.
- `git diff --check` - exit **0**; only pre-existing line-ending warnings for
  generated schema files and touched text files.

## Final independent approval - 2026-07-12

- Fresh reviewer `/root/task6_workflow_reviewer_final` (gpt-5.6-sol,
  independent reviewer role) returned separate **SPEC PASS** and **CODE PASS**
  verdicts with **READY: yes**.
- No Critical, Important or Minor findings remain. The reviewer confirmed the
  spec file and schema files equal their index blobs and must remain unstaged;
  only the dashboard/test content diff and the four intended Task 6 evidence
  files are in scope.
