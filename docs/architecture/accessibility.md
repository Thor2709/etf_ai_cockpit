# Accessibility and responsive layout contract

This document records the UI quality gate for `ISSUE-0041`. The application
is local-first and advisory-only: accessibility behaviour must not grant
execution authority, change a score, or invent unavailable evidence.

## Presentation policy

The current Flet shell is deliberately dark-mode-first. `initialise_page`
selects `ft.ThemeMode.DARK` and applies the shared palette from
`src/etf_cockpit/app/theme.py`. Primary and semantic text colours are checked
against the `#101114` background by
`tests/test_accessible_table.py::test_dark_palette_text_and_semantic_states_meet_wcag_aa`;
the tested minimum is WCAG AA (4.5:1) for normal text. State meaning is also
rendered as text, so colour is never the sole carrier of status. A selectable
light-mode palette is not currently part of the product contract and must not
be implied by screenshots or exports.

## Responsive and keyboard behaviour

The shell keeps the same route groups at desktop and narrow widths. At the
narrow breakpoint the sidebar is replaced by a collapsed mobile navigation
tile; the command palette remains a labelled text input and supports filtering
and Enter-to-navigate. Wrapping action rows use fixed-width controls and do
not place `expand=True` children inside `ft.Row(wrap=True)`.

## Table behaviour

`accessible_table` is the text-first table contract:

- search is case-insensitive, trims surrounding whitespace, and treats user
  punctuation literally (it is not a regular expression);
- sortable columns exclude structured cells and use stable ordering with
  missing values last;
- search and sort callbacks refresh visible rows and the textual row-count
  status; detached Flet controls may defer their redraw until mounted;
- labels and sort tooltips remain available to assistive and keyboard users.

The focused component tests cover these behaviours. The broader responsive,
navigation, accessibility-contract and button-contract suites remain the
regression gate for changes to shared UI components.
