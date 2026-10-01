# Dashboard typed commands

Dashboard workflow buttons submit `DashboardActionCommand` with the
`dashboard_action` kind through `AppState.application_api`. The registered
handler calls the existing `AppState` methods for yfinance refresh, algorithm
and forecast runs, data validation, provider status, price rollback, audit
export, and local import validation or upload. Commands return readable result
details; failures return `FAILED` with an error message for the activity panel.
Each attempt uses a new idempotency key. `SubmitWorkflowCommand` remains on the
durable scheduler path. “Show scores” remains navigation to `/signals`, not a
background job. UI actions retain `execution_allowed=false`.
