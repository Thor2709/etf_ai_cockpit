# Wave 1 Governance Task 5 report

## RED evidence

- Command: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/ui/test_system_map_ui.py tests/ui/test_help_glossary_ui.py tests/ui/test_decision_journal_ui.py tests/ui/test_authority_gate_ui.py`
- Exit: **1** during collection, with genuine missing-module failures for the
  four new governance surfaces (`system_map`, `help_glossary`,
  `decision_journal` and `governance_badges`).

Implementation and GREEN evidence will be appended after the focused tests and
boundary checks pass.

## GREEN and boundary evidence - 2026-07-12

- Implemented reusable `status_badge`/`build_gate_summary`, System Map,
  Help/Glossary and user-owned Decision Journal pages, plus `/system-map`,
  `/help` and `/decision-journal` routes.
- Focused UI GREEN: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/ui/test_system_map_ui.py tests/ui/test_help_glossary_ui.py tests/ui/test_decision_journal_ui.py tests/ui/test_authority_gate_ui.py` - exit **0**, 4 passed.
- Affected UI/release/boundary bundle: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/test_accessibility_contracts.py tests/test_flet_startup.py tests/ui tests/scope_boundary` - exit **0**, 41 passed.
- Compileall and scoped Ruff over Task 5 source/tests - exit **0**; `All checks passed!`.
- Static boundary evidence generated at
  `evidence/governance/execution_boundary_report.json`: `result=pass`, 425
  files scanned, zero violations.
- Source smoke: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe scripts\\run_app.py --smoke` - exit **0**, `snapshot_ok as_of=2026-07-10 signals=16 backtests=5`.
- `execution_allowed` remains `false`; no broker, credentials, order routing or
  execution controls were added.

## Independent review and fix-pass evidence - 2026-07-12

- Review 1 rejected the implementation for missing feature-registry route
  entries, non-actionable glossary/gate navigation, and a journal list that did
  not refresh after saving. Review 2 additionally required per-dependency
  readiness, explicit registry limitations, hash-targeted glossary navigation,
  keyboard-operable shell navigation, and read-failure states.
- Fix pass: added exact registry entries for all 25 routes and typed
  `limitations`; added per-dependency readiness and data-health validation to
  System Map; added `/help#<term>` selection; changed shell navigation to
  focusable `TextButton`s; wired the Scores gate summary to
  `/help#manual_review`; and rendered partial/error states for journal read
  failures while refreshing recent entries after a successful save.
- Final fresh independent reviewer: **SPEC PASS, CODE PASS, READY YES**;
  Critical/Important/Minor findings: none.
- Final focused and affected bundle: `pytest -q tests/ui
  tests/test_accessibility_contracts.py tests/test_flet_startup.py
  tests/test_feature_registry.py tests/scope_boundary` - exit **0**, 50
  passed.
- Compileall and scoped Ruff: exit **0**, `All checks passed!`.
- Static boundary report: `result=pass`, 425 files scanned, zero violations;
  `execution_allowed=false`, `executable_authority=false`.
- Source smoke: `scripts\\run_app.py --smoke` - exit **0**,
  `snapshot_ok as_of=2026-07-10 signals=16 backtests=5`.
- Browser/source visual evidence on local web build at `http://127.0.0.1:8555`:
  System Map and `/help#manual_review` rendered successfully. Artefacts:
  `evidence/governance/task5-system-map.png` SHA-256
  `849596694A1523D50157529097616096EF6F0F61ACEA9E70AC1229EE297F8B3A` and
  `evidence/governance/task5-help-glossary.png` SHA-256
  `EA55CA3AA38D48A83D08CBA2427DC48DAF9373AB924A119F158A63318E468D04`.
- Authoritative full-suite run completed with seven environment/data-fixture
  failures in the worktree because the ignored `data/raw/trade_candidates`
  fixture is absent and the static identity artefact has 16 rather than the
  expected 45 rows; these are recorded as pre-existing repository-fixture
  failures and are not caused by Task 5 source changes. The same targeted
  simple-score/trust tests pass on clean `main`, where those ignored fixtures
  are present. Task 5 introduces no new failure in its affected bundle.
