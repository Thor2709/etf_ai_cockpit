# Macro and Factors warehouse

The local Macro and Factors workspace reads saved source payloads through
`MacroWarehouse`. It does not call remote providers and does not create trading
authority. World Bank-shaped JSON and a documented local CSV shape are supported
as parser inputs; source terms and checksums remain attached to every batch.

Observations are written to the existing append-only bitemporal ledger. Each row
has an effective period and an explicit `available_at` timestamp. An as-of query
therefore selects only the latest active revision known at the decision time.
Current revised values cannot silently replace historical evidence.

Unit conversion and monthly-to-quarterly/annual aggregation create derived rows
with a transformation version and the source observation IDs. The raw rows
remain in the ledger, making the transformation auditable and reversible by
replaying the source observations. Missing country or currency context is shown
as `unavailable_context`, not inferred or filled with a substitute.

The first slice covers the warehouse contract and read-only workspace. Remote
provider scheduling, broad source coverage and downstream risk/benchmark
consumers remain later work.
