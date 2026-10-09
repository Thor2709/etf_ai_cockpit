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

The ETF E1 read model uses `load_etf_e1_fields` for per-field issuer-document,
public-page and yfinance precedence. Only observations with a source, effective
date and known-at time at or before the decision are eligible. Lower-priority
values remain alternates, and disagreements are visible. Missing fields carry
reason codes. These display fields do not promote vendor data into canonical
tracking or scoring evidence. Explicit source readers in
`fetch_etf_economics_sources` support offline fixtures; issuer/public acquisition
requires real source bindings and does not construct URLs from identifiers.

Legacy reference rows can obtain their acquisition time from a matching
reference-import manifest, checked against the frame checksum. A retrieval date
is vendor observation context, not a verified issuer publication date. The AUM
normaliser preserves `aum`/`total_assets` in currency units and preserves an
explicit AUM currency; the trading currency is never substituted for it.

Tracking difference has one calculation: `calculate_etf_economics` subtracts
index total return from ETF total return over the same stated business-day
window. Both series require the existing canonical corporate-action binding,
matching currencies and return convention. Missing index evidence produces no
tracking result, even when ETF prices are available.

Holdings select one effective, known vintage and source. Country and sector
weights derive from that snapshot, with undisclosed/unclassified weight shown
as `Other/unclassified`; unusable weights remain unavailable. Issuer splits
are the fallback when holdings are unavailable. ETF pages render E1 tiles,
the top 25 disclosed holdings with a count, labelled split charts and a
deterministic summary through the existing kit.

Sectors & Countries reuses the canonical exposure cube and dated stock
classification resolver. With no portfolio holdings, it uses equal weights
over enabled instruments and labels the view
`Universe (no portfolio holdings registered)`. Registering holdings restores
portfolio weights. Unknown classifications are explicit exposure, not inferred
countries or sectors. A sector-by-metric heatmap shows exposure and the mean
available canonical attractiveness for configured sector peers, with score
coverage and unavailable reasons. No new instrument score formula is introduced.
