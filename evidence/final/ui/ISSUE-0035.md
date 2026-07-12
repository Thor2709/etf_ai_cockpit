# ISSUE-0035 UI gate

Source Flet browser render at `/data-health` showed the dark research-cockpit
shell, Data Health title, export action, inventory cards, explicit statuses,
filters and related actions. The packaged render at the same route showed the
same surface and content. Evidence files are:

- `evidence/final/browser/ISSUE-0035-desktop.png`
- `evidence/final/browser/ISSUE-0035-mobile.png`
- `evidence/final/browser/ISSUE-0035-packaged.png`

The source app was loaded at `http://127.0.0.1:8602/data-health`; enabling the
Flet accessibility semantics exposed labelled navigation, `Data Health`,
`Export health CSV`, status/dataset/provider filters, per-row provider/status/
filings/ETF/errors actions, and migration status controls. Pressing `Tab`
advanced through the semantic tree and the page exposed the expected
focusable controls. The source and packaged browser logs contained only the
expected `Flutter app loaded` message. Final integration and synchronisation
remain pending.
