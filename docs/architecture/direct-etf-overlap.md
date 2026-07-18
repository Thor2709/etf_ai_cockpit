# Direct ETF overlap boundary

`ISSUE-0022` initially exposes deterministic, local direct-holdings overlap on Portfolio, Risk and Instrument Detail. It is research evidence only and always records `execution_allowed=false`.

The calculation selects one latest non-future snapshot per ETF, rejects equal-authority conflicts, and matches only typed identities: valid ISINs or explicitly namespaced provider, security or venue-qualified ticker identifiers. Pair overlap is the sum of the smaller disclosed weight for each shared identity. Partial or unresolved holdings are never renormalised.

Coverage and freshness remain separate. Freshness is recomputed from the selected as-of date on every query rather than trusted from persisted text. Full, fresh snapshots with a source identifier and uniform recognised authority can report current direct overlap. Partial snapshots report an observed dated lower bound. Stale snapshots may show dated observations but explicitly make current overlap unavailable. Missing, malformed, future-dated, unprovenanced or conflicting evidence returns `N/A`, not zero.

Generic user imports are `manual_unverified`; authority cannot be supplied by an imported source column or editable UI text. Canonical decimal weights reject Python or NumPy booleans, non-finite values, negatives and implicit percentages. Results include opaque source identifiers and deterministic checksums, not local paths. `fund_holdings` is authoritative per instrument; the older `etf_holdings` store can fill only instruments absent from canonical data and is adapted read-only as partial, unverified evidence after independent local-path containment checks.

Recursive nested funds, derivative-underlying inference, short exposure, complete holdings history and factor/valuation propagation remain later `ISSUE-0022`/`ISSUE-0105` work. Direct fund shares and untyped cash or derivatives remain unresolved in this slice.
