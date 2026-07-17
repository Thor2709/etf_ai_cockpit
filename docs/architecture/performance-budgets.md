# Local performance budgets

The performance policy in `configs/performance_budgets.yaml` is versioned with
the application. It defines startup, first durable event, route render, local
query and refresh budgets, representative 100/1,000/10,000-instrument screen
datasets, backtest and optional training limits, peak memory and local storage.

`etf_cockpit.core.performance` consumes the existing local JSONL timing/cache
trace and adds peak Python allocation and storage evidence. It emits the
`performance-budgets.v1` JSON and Markdown reports. The release gate runs the
checker as a mandatory local check; any observed value beyond its budget
tolerance returns a non-zero status. Missing measurements remain visible as
`unmeasured`, so a release is not presented as benchmark-complete when a
workflow has not run.

The Diagnostics route displays the report status, failure count, storage size,
cache counters and the explicit `network_calls=false` boundary. This is
diagnostic evidence only: it does not replace numerical implementations,
change risk gates or send telemetry outside the local application.
