# Execution-cost model

ISSUE-0128 provides one deterministic, local-only cost estimate for score netting, portfolio rebalance previews and historical backtests. It is an estimate, not a broker order or a realised fill.

`etf_cockpit.portfolio.costs` combines fixed commission, configured or imported spread and slippage, volatility/volume impact, square-root impact, FX and gap stress. Order value is absolute, so buy and sell estimates are symmetric. Cost in EUR is monotonic with order size for the same assumptions. A configured maximum participation rate produces a capacity estimate when local ADV evidence is available.

Missing ADV or volatility does not silently produce a clean result. The model applies a conservative impact floor, increases the uncertainty multiplier and labels the estimate `degraded_missing_microstructure`. Completed local quote or fill calibration can be passed explicitly to a new estimate without changing prior estimates.

Backtest trade rows retain the model ID, estimate quality, capacity and estimated basis points. `compare_realised_fill` returns separate transaction-cost analysis evidence keyed to the immutable estimate ID. No function in this module fetches data, submits orders or grants execution authority; all outputs set `execution_allowed=false`.
