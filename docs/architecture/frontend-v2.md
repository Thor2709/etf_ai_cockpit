# Frontend v2 foundation

ISSUE-0137 establishes the first application-wide presentation contract. It is
an incremental Flet implementation, not a replacement frontend or a complete
design-system migration.

## Technology decision

Flet remains the selected frontend for this phase. The existing application,
route builders, component library and startup path already run in Flet, so the
initial slice adds no frontend dependency, no build pipeline and no duplicated
API boundary. React/Tauri remains a measured proof-of-concept decision for a
later phase: it must demonstrate a material benefit against the current Flet
shell before introducing a second runtime and its supply-chain intake.

Measured costs for this slice are deliberately small and reproducible:

| Measure | Result | Evidence |
| --- | --- | --- |
| New production frontend dependencies | 0 | `pyproject.toml` and the package lock remain unchanged |
| New frontend runtime/build pipelines | 0 | the existing Flet startup path is retained |
| Information-architecture groups | 9 | `WORKSPACE_GROUPS` in `app/router.py` |
| Explicit evidence states | 5 | `app/components/states.py` |
| Evidence density modes | 3 | `theme.EVIDENCE_MODES` |

The measured local app smoke and focused tests are the release evidence for the
remaining runtime cost. A React/Tauri POC should be added only with its own
ADR, timing comparison, accessibility evidence and dependency intake record.

## Visual specification

The shell uses a dark, high-contrast surface hierarchy. Decision content is
the page title and primary summary; uncertainty is expressed in the state
label, warning/error text and evidence-mode description; supporting evidence
and diagnostics remain selectable text. Colour is supplementary: every state
also says `State: empty`, `State: loading`, `State: success`, `State: warning`
or `State: error`.

Shared tokens are in `app/theme.py`:

- spacing: 4, 8, 12, 16, 24 and 32 px;
- radii: 6, 8 and 12 px;
- type sizes: 11, 12, 14, 17 and 20 px;
- semantic colours for state, action and severity.

The shell groups existing routes into Home, Discover, Instrument, Portfolio,
Models, Backtest/Paper, Data Health, Audit and Settings. Mobile layouts keep
the same groups and wrap navigation controls instead of hiding routes.

The initial Discover comparison workspace aligns two canonical local score
objects in a text-first table. It reports units, coverage, data date and
execution authority explicitly and can save the selected pair to the local
workspace store for later reproduction.

## Evidence modes

- Compact - decision summary for quick scanning.
- Default - decision, uncertainty and supporting evidence (the default).
- Advanced - evidence plus diagnostic detail.

Changing the mode changes presentation state only. It cannot start a workflow,
change a score, bypass a risk gate or grant execution authority.

## Component catalogue

| Component | Contract | Typical use |
| --- | --- | --- |
| `panel` | bordered surface with consistent padding | page sections |
| `metric_card` | labelled value and status subtitle | dashboard summary |
| `section_header` | title plus explanatory context | evidence sections |
| `evidence_chip` | text label, value and supplementary colour | small evidence facts |
| `state_panel` | explicit state, title, message and optional details/action | empty/loading/success/warning/error |
| `accessible_table` | selectable text, search and deterministic sort metadata | evidence tables |
| chart descriptors | text-first series summary and export identity | charts and backtests |

Later issues may add visual regression capture, richer responsive layouts and
route-by-route migration. Those are intentionally outside this foundation.
