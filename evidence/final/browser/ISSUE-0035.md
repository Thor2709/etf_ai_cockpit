# ISSUE-0035 browser gate

Playwright loaded the rebuilt packaged native app at `http://127.0.0.1:8593/data-health`, waited for the Flet title and captured desktop and 1040px screenshots. It then loaded `/` and captured the Dashboard `Data health` summary. Local HTTP readiness passed, and the browser console returned zero errors for the route checks.

Visual evidence is preserved in `ISSUE-0035-data-health-desktop.png`, `ISSUE-0035-data-health-1040px.png`, `ISSUE-0035-dashboard-summary.png` and `ISSUE-0035-console.log`. The Flet semantic snapshot was limited to the accessibility toggle. A Computer Use retry stopped before input with a URL-confidence policy error; no Computer Use pass is claimed.
