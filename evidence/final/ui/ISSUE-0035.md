# ISSUE-0035 UI gate

Source Flet browser render at `/data-health` showed the dark research-cockpit
shell, Data Health title, export action, inventory cards, explicit statuses,
filters and related actions. The packaged render at the same route showed the
same surface and content. Evidence files are:

- `evidence/final/browser/ISSUE-0035-desktop.png`
- `evidence/final/browser/ISSUE-0035-mobile.png`
- `evidence/final/browser/ISSUE-0035-packaged.png`

The Flet semantic snapshot exposed only the accessibility-toggle control;
canvas semantics were not available for deeper assertions. The source and
packaged browser logs contained only the expected `Flutter app loaded` message.
Keyboard/focus semantics therefore remain closure-pending rather than claimed
as a pass.
