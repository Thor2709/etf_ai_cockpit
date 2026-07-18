# ETF liquidity and economics

`etf_cockpit.features.etf_economics` provides deterministic, local-only ETF
liquidity evidence for Instrument Detail. It uses validated OHLCV history and
optionally reads `data/raw/etf_quotes/quotes.csv` (or the same file as
`quotes.parquet`) when the user has imported quote evidence.

The price-only calculation reports 20-day and 60-day rolling traded value,
median volume, zero-volume frequency, high/low spread proxies, gap-risk
percentiles and daily adjusted-price volatility. Capacity is order-size and
horizon specific: rolling exchange traded value is multiplied by the
configured maximum participation rate and the requested horizon. An order
preview above that policy capacity is labelled `blocked_liquidity_policy`.

Optional quote rows may contain `instrument_id`, `quote_timestamp`, `session`,
`bid`, `ask`, `nav`, `underlying_adv_eur`,
`primary_market_capacity_eur`, `primary_market_minimum_eur`, `source_id` and
`source_authority`. Missing bid/ask, NAV or timestamp evidence remains
explicit. A quote is marked stale after 24 hours relative to the selected
price as-of and is marked off-hours only when the imported session says so;
the application does not invent an exchange calendar or real-time depth.

Exchange capacity and primary-market capacity are separate fields. The latter
is informational context for creations/redemptions and is never substituted
for exchange volume. Cost estimates reuse the ISSUE-0128 model and show a
stress value alongside the base value. Every panel and preview sets
`execution_allowed=false`.
