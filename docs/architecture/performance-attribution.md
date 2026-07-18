# Performance and decision attribution

ISSUE-0116 adds a local, read-only attribution contract to the Risk Evidence
workspace. It links adjusted-price observations through portfolio wealth so
asset contributions plus the explicit cash component reconcile to the gross
time-weighted return. It can additionally consume dated benchmark, factor,
cost, cashflow and decision-journal frames supplied by the application layer.

Missing evidence is not filled: money-weighted performance requires dated
external cashflows, currency attribution is labelled an instrument-bucket
proxy until an FX series is supplied, and costs, taxes, fills and decision
links remain unavailable unless explicit local records exist. The report is
descriptive evidence only and always carries `execution_allowed=false`.
