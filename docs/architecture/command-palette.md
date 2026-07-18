# Command palette

The application shell exposes a local command palette in the header. It
searches the registered page titles, routes and workspace names in the same
order as `WORKSPACE_GROUPS`. Selecting a result or submitting the first result
navigates through the existing router, so route changes retain the normal
session event and state handling.

The palette is presentation-only. It does not execute commands, change
authority, access a network provider or persist user data. Unknown searches
remain readable and do not fall back to an unrelated route.
