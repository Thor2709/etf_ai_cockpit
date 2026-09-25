# Deterministic event-driven backtest

ISSUE-0125 adds a local order-level replay contract in
`src/etf_cockpit/backtest/event_engine.py`. It accepts immutable historical
market, signal, target, proposal, order and lifecycle events and emits
acknowledgements, fills, cancellations and expiries in deterministic order.

The replay uses a weekday session calendar, rejects unlisted or unsupported
market data, prevents same-timestamp fills, supports market and limit orders,
and caps each fill by optional historical liquidity. Replaying the same events
produces the same ledger hash, independent of input order.

`execution_allowed` remains permanently false. The module is local-only and
does not fetch data, transmit orders or create broker/paper authority. The
Backtests page exposes the supported lifecycle and safety boundary while the
existing aggregate report remains visible as a separate evidence product.

## Operational decision-price evidence (ISSUE-0050)

The vector backtest records one instrument-scoped operational evidence row per
traded instrument and rebalance. A signal at the adjusted close of session *t*
is executed no earlier than the next canonical market session: same-bar
execution is forbidden, `execution_delay_sessions` is 1 only for a verified next
session, and `same_bar_execution_avoided` is false whenever that cannot be
proved. Each row shows the signal timestamp, decision price (adjusted close),
next-open reference (raw open scaled by the same row's adjusted-close factor),
next-period adjusted close, close-to-next-open gap, arrival-price assumption,
high/low range spread proxy and cost assumptions with their sources. Missing
OHLC, calendar or source identity leaves the row explicitly unavailable.

`open_gap_warning` flags `|close_to_next_open_gap| >= open_gap_warning_threshold`
(`CostModel.open_gap_warning_threshold`, default 0.02, validated `0 < t <= 1`). The
shipped `configs/costs.yaml` does not set it, so the settings companion revision
of existing installations stays valid; an override belongs in
`cost_model.open_gap_warning_threshold` through the normal settings save path.
It is display-only: it never gates, reprices, changes costs or grants execution
authority, and an unavailable gap leaves the warning unavailable. The same
evidence appears on Backtests, Signals and Instrument Detail.

Related: ISSUE-0005 (friction/cost/slippage stress engine, which supplies the
cost assumptions shown here) and ISSUE-0028 (backtest lab upgrade, which owns
the broader backtest surface). `execution_allowed` remains false.
