# Wave 1 Governance Task 5 brief

## Scope

Implement only the approved governance surfaces and static release boundary
from the governance plan. Preserve the dark evidence-cockpit Flet shell,
existing theme/tokens, route patterns and authority boundary. `execution_allowed`
must remain `false`; no broker, order routing, credentials or execution controls.

## Required deliverable

Create:

- `src/etf_cockpit/app/pages/system_map.py`
- `src/etf_cockpit/app/pages/help_glossary.py`
- `src/etf_cockpit/app/pages/decision_journal.py`
- `src/etf_cockpit/app/components/governance_badges.py`
- `tests/ui/test_system_map_ui.py`
- `tests/ui/test_help_glossary_ui.py`
- `tests/ui/test_decision_journal_ui.py`
- `tests/ui/test_authority_gate_ui.py`

Modify only the seams required to expose these pages and reusable badges:

- `src/etf_cockpit/app/router.py`
- `src/etf_cockpit/app/flet_app.py` if route setup needs it
- score/portfolio/instrument pages only for real deep-links to governance
  surfaces
- `README.md` and audit templates only for documented routes/contracts

## Observable contracts

- `/system-map` displays lifecycle, authority, data/validation status, direct
  route and limitation cards; future execution is visibly `Not installed` and
  non-interactive; no `Enable trading` or order action text.
- `/help` or `/glossary` provides glossary anchors for lifecycle, authority,
  gate severity and unavailable/manual-review states; links are keyboard
  focusable and semantic.
- `/decision-journal` displays user-owned local notes/outcomes with one clear
  primary save action, explicit local-only/no-execution language, unavailable,
  empty, success, partial and error states; use `DecisionJournal` from Task 4,
  never a broker or mutable execution path.
- Gate/research surfaces have a reusable `build_gate_summary`/badge contract
  with text and icon semantics, keyboard focus and visible state; `View all
  gates` is focusable.
- Routes are in `router.PAGES`, use existing theme tokens and preserve narrow
  responsive shell behaviour.
- Static execution-boundary tests pass and a current report is generated with
  `python -m etf_cockpit.governance.static_checks --root . --output evidence/governance/execution_boundary_report.json`.

## RED-GREEN-REFACTOR

Write focused UI/wording tests first and run:

`..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/ui/test_system_map_ui.py tests/ui/test_help_glossary_ui.py tests/ui/test_decision_journal_ui.py tests/ui/test_authority_gate_ui.py`

RED must fail because the pages, route entries and semantic controls do not
exist. Implement the smallest reusable components/pages, then rerun focused,
affected and scope-boundary tests. Record exact evidence in
`.ai_worklog/task-governance-5-report.md` and obtain independent review.

## Forbidden scope

No DATA-05 changes, scoring changes, portfolio targets, model authority,
research thresholds, credentials, broker APIs, execution controls or unrelated
UI redesign.
