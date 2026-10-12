# Issue #245 safe-point handoff

The look-through projection now aggregates explicitly reported industry,
domicile, economic-currency, factor, and cap-bucket labels alongside the
existing issuer, sector, country, reported-currency, and listing dimensions.
It reports covered weight and an available, partial, or unavailable state per
dimension. Missing or conflicting labels are omitted and described; they are
never assigned a default bucket.

The selected metric scope remains covered-weight earnings-yield P/E for value
and covered-constituent arithmetic ROIC for quality. Both retain point-in-time
availability/effective-date filtering and per-metric coverage. No momentum,
volatility, standardized factor score, or missing-value imputation is inferred
from these inputs. The existing 90-day holdings freshness default remains in
place.

Instrument Detail now loads the local facade at the snapshot decision time and
renders its result in the Fund section. The facade and calculations remain
read-only with `execution_allowed=false`.

Safe point reached on synthetic fixtures. Real ETF/share-class source evidence,
canonical-master alias coverage, owner-defined full-parent scope, and real-data
acceptance are still required before issue #245 can be marked complete.
