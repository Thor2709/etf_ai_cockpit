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
